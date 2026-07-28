"""Authenticated, short-lived WebSocket transport."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


CHANNEL_MIN_ROLES = {
    "server_status": "viewer",
    "traffic": "viewer",
    "snapshot_delta": "viewer",
    "clients": "operator",
    "inbounds": "operator",
}


def build_realtime_router(
    *,
    check_basic_auth_header,
    verify_totp_code,
    verify_ws_ticket,
    get_user_role,
    ws_manager,
    handle_websocket_message,
    logger,
):
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        protocols = websocket.headers.get("sec-websocket-protocol", "")
        ticket = next(
            (item[len("mssg-ticket."):]
             for item in (part.strip() for part in protocols.split(","))
             if item.startswith("mssg-ticket.") and len(item) > len("mssg-ticket.")),
            None,
        )
        user = verify_ws_ticket(ticket)
        if not user:
            await websocket.close(code=1008)
            return

        role = get_user_role(user)

        accepted_protocol = f"mssg-ticket.{ticket}"
        await websocket.accept(subprotocol=accepted_protocol)
        await ws_manager.connect(websocket, accept=False, user=user, role=role)
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") in {"subscribe", "unsubscribe"}:
                    channel = str(data.get("channel") or "")
                    minimum_role = CHANNEL_MIN_ROLES.get(channel)
                    if not minimum_role or not ws_manager.has_channel_access(role, minimum_role):
                        await websocket.close(code=1008)
                        return
                await handle_websocket_message(websocket, data)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as exc:
            logger.error("WebSocket error: %s", exc)
            ws_manager.disconnect(websocket)

    return router
