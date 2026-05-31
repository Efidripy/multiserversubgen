import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


WS_AUTH_TIMEOUT_SEC = 5


def build_realtime_router(
    *,
    check_basic_auth_header,
    verify_totp_code,
    mfa_totp_ws_strict,
    pam_authenticate,
    ws_manager,
    handle_websocket_message,
    logger,
):
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        auth_message = None
        user = check_basic_auth_header(websocket.headers.get("Authorization"))
        if not user:
            await websocket.accept()
            try:
                auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=WS_AUTH_TIMEOUT_SEC)
                if auth_message.get("type") == "auth":
                    username = str(auth_message.get("username") or "")
                    password = str(auth_message.get("password") or "")
                    if username and password and pam_authenticate(username, password):
                        user = username
            except Exception:
                user = None
        if not user:
            await websocket.close(code=1008)
            return

        ws_totp_code = websocket.headers.get("X-TOTP-Code")
        if not ws_totp_code and auth_message:
            ws_totp_code = auth_message.get("totp")
        if mfa_totp_ws_strict:
            if not verify_totp_code(user, ws_totp_code):
                await websocket.close(code=1008)
                return
        elif ws_totp_code:
            if not verify_totp_code(user, ws_totp_code):
                await websocket.close(code=1008)
                return

        await ws_manager.connect(websocket, accept=auth_message is None)
        try:
            while True:
                data = await websocket.receive_json()
                await handle_websocket_message(websocket, data)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as exc:
            logger.error(f"WebSocket error: {exc}")
            ws_manager.disconnect(websocket)

    return router
