import datetime

from fastapi import APIRouter, HTTPException, Request


def build_auth_router(
    *,
    check_auth,
    verify_totp_code,
    get_user_role,
    issue_ws_ticket,
    mfa_totp_enabled,
    monitoring_enabled,
):
    router = APIRouter()

    @router.get("/api/v1/health")
    @router.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}

    @router.get("/api/v1/auth/verify")
    async def verify_auth(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not verify_totp_code(user, request.headers.get("X-TOTP-Code")):
            raise HTTPException(status_code=401, detail="MFA required")
        role = getattr(request.state, "auth_role", None) or get_user_role(user)
        return {
            "user": user,
            "role": role,
            "mfa_enabled": mfa_totp_enabled,
            "ws_ticket": issue_ws_ticket(user),
        }

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
