import base64

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


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
        user = check_basic_auth_header(websocket.headers.get("Authorization"))
        if not user:
            token = websocket.query_params.get("token")
            if token:
                try:
                    decoded = base64.b64decode(token).decode("utf-8")
                    username, password = decoded.split(":", 1)
                    if pam_authenticate(username, password):
                        user = username
                except Exception:
                    user = None
        if not user:
            await websocket.close(code=1008)
            return

        ws_totp_code = websocket.query_params.get("totp") or websocket.headers.get("X-TOTP-Code")
        if mfa_totp_ws_strict:
            if not verify_totp_code(user, ws_totp_code):
                await websocket.close(code=1008)
                return
        elif ws_totp_code:
            if not verify_totp_code(user, ws_totp_code):
                await websocket.close(code=1008)
                return

        await ws_manager.connect(websocket)
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
