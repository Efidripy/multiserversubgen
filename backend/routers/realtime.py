"""Authenticated, short-lived WebSocket transport."""

import json
import os
from threading import Lock

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


CHANNEL_MIN_ROLES = {
    "server_status": "viewer",
    "traffic": "viewer",
    "snapshot_delta": "operator",  # carries the clients and inbounds tables
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
    max_per_user = max(1, int(os.getenv("WS_MAX_CONNECTIONS_PER_USER", "20")))
    max_total = max(1, int(os.getenv("WS_MAX_CONNECTIONS_TOTAL", "500")))
    max_message_bytes = max(1, int(os.getenv("WS_MAX_MESSAGE_BYTES", "65536")))
    connection_lock = Lock()
    connections: dict[str, int] = {}


    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        protocols = websocket.headers.get("sec-websocket-protocol", "")
        ticket = next(
            (
                item[len("mssg-ticket.") :]
                for item in (part.strip() for part in protocols.split(","))
                if item.startswith("mssg-ticket.") and len(item) > len("mssg-ticket.")
            ),
            None,
        )
        user = verify_ws_ticket(ticket)
        if not user:
            await websocket.close(code=1008)
            return

        with connection_lock:
            admitted = sum(connections.values()) < max_total and connections.get(user, 0) < max_per_user
            if admitted:
                connections[user] = connections.get(user, 0) + 1
        if not admitted:
            await websocket.close(code=1013)
            return

        connected = False
        try:
            role = get_user_role(user)

            # Avoid echoing the ticket when the fixed protocol is offered.
            accepted_protocol = (
                "mssg-ws" if "mssg-ws" in {p.strip() for p in protocols.split(",")} else f"mssg-ticket.{ticket}"
            )
            await websocket.accept(subprotocol=accepted_protocol)
            connected = True
            await ws_manager.connect(websocket, accept=False, user=user, role=role)
            while True:
                text = await websocket.receive_text()
                if len(text.encode("utf-8")) > max_message_bytes:
                    await websocket.close(code=1009)
                    return
                data = json.loads(text)
                if data.get("type") in {"subscribe", "unsubscribe"}:
                    channel = str(data.get("channel") or "")
                    minimum_role = CHANNEL_MIN_ROLES.get(channel)
                    if not minimum_role or not ws_manager.has_channel_access(role, minimum_role):
                        await websocket.close(code=1008)
                        return
                await handle_websocket_message(websocket, data)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("WebSocket error: %s", exc)
        finally:
            try:
                if connected:
                    ws_manager.disconnect(websocket)
            finally:
                with connection_lock:
                    connections[user] -= 1
                    if not connections[user]:
                        del connections[user]

    return router
