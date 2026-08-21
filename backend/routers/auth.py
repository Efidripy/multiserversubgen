import datetime

from fastapi import APIRouter, HTTPException, Request, Response


def build_auth_router(
    *,
    check_auth,
    verify_totp_code,
    get_user_role,
    issue_ws_ticket,
    issue_web_session,
    web_session_cookie_name,
    web_session_ttl_sec,
    web_path,
    mfa_totp_enabled,
    monitoring_enabled,
):
    router = APIRouter()
    cookie_path = f"/{web_path.strip('/')}/" if web_path.strip("/") else "/"

    def _auth_payload(user: str, role: str):
        return {
            "user": user,
            "role": role,
            "mfa_enabled": mfa_totp_enabled,
            "ws_ticket": issue_ws_ticket(user),
        }

    @router.get("/api/v1/health")
    @router.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}

    @router.get("/api/v1/auth/verify")
    async def verify_auth(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not getattr(request.state, "auth_mfa_ok", False) and not verify_totp_code(user, request.headers.get("X-TOTP-Code")):
            raise HTTPException(status_code=401, detail="MFA required")
        role = getattr(request.state, "auth_role", None) or get_user_role(user)
        return _auth_payload(user, role)

    @router.post("/api/v1/auth/session")
    async def create_web_session(request: Request, response: Response):
        user = check_auth(request)
        if not user or getattr(request.state, "auth_via", None) != "basic":
            raise HTTPException(status_code=401, detail="Basic authentication required")
        if not getattr(request.state, "auth_mfa_ok", False):
            raise HTTPException(status_code=401, detail="MFA required")
        role = getattr(request.state, "auth_role", None) or get_user_role(user)
        response.set_cookie(
            key=web_session_cookie_name,
            value=issue_web_session(user),
            max_age=web_session_ttl_sec,
            path=cookie_path,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return _auth_payload(user, role)

    @router.post("/api/v1/auth/logout")
    async def logout_web_session(response: Response):
        response.delete_cookie(
            key=web_session_cookie_name,
            path=cookie_path,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return {"status": "ok"}

    @router.get("/api/v1/auth/mfa-status")
    async def mfa_status():
        return {"enabled": mfa_totp_enabled}

    @router.get("/api/v1/features")
    async def features(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {
            "monitoringEnabled": bool(monitoring_enabled),
            "mfaEnabled": bool(mfa_totp_enabled),
        }

    return router
