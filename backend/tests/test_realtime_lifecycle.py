"""Lifecycle regressions for the authenticated WebSocket endpoint."""

import asyncio
import json
import os
import sys

from fastapi import WebSocketDisconnect

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.realtime import build_realtime_router


class _FakeWebSocket:
    def __init__(self, messages):
        self.headers = {"sec-websocket-protocol": "mssg-ticket.ticket"}
        self._messages = iter(messages)
        self.accepted_subprotocol = None
        self.close_codes = []

    async def accept(self, *, subprotocol):
        self.accepted_subprotocol = subprotocol

    async def close(self, *, code):
        self.close_codes.append(code)

    async def receive_text(self):
        message = next(self._messages)
        if isinstance(message, BaseException):
            raise message
        return json.dumps(message, ensure_ascii=False)


class _FakeConnectionManager:
    def __init__(self, *, channel_access=True):
        self.active_connections = set()
        self.channel_access = channel_access
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self, websocket, *, accept, user, role):
        assert accept is False
        assert (user, role) == ("user", "viewer")
        self.connect_calls += 1
        self.active_connections.add(websocket)

    def disconnect(self, websocket):
        self.disconnect_calls += 1
        self.active_connections.discard(websocket)

    def has_channel_access(self, _role, _minimum_role):
        return self.channel_access


class _FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, *args):
        self.errors.append(args)


def _websocket_endpoint(manager, handler):
    router = build_realtime_router(
        check_basic_auth_header=lambda _header: None,
        verify_totp_code=lambda _user, _code: True,
        verify_ws_ticket=lambda ticket: "user" if ticket == "ticket" else None,
        get_user_role=lambda _user: "viewer",
        ws_manager=manager,
        handle_websocket_message=handler,
        logger=_FakeLogger(),
    )
    return router.routes[0].endpoint


def _assert_disconnected_once(manager, websocket):
    assert manager.connect_calls == 1
    assert manager.disconnect_calls == 1
    assert websocket not in manager.active_connections


def test_policy_close_after_connect_removes_invalid_subscription_once():
    manager = _FakeConnectionManager()
    websocket = _FakeWebSocket([{"type": "subscribe", "channel": "unknown"}])

    asyncio.run(_websocket_endpoint(manager, lambda *_args: None)(websocket))

    assert websocket.close_codes == [1008]
    _assert_disconnected_once(manager, websocket)


def test_policy_close_after_connect_removes_role_denied_unsubscribe_once():
    manager = _FakeConnectionManager(channel_access=False)
    websocket = _FakeWebSocket([{"type": "unsubscribe", "channel": "clients"}])

    asyncio.run(_websocket_endpoint(manager, lambda *_args: None)(websocket))

    assert websocket.close_codes == [1008]
    _assert_disconnected_once(manager, websocket)


def test_disconnect_after_connect_removes_socket_once():
    manager = _FakeConnectionManager()
    websocket = _FakeWebSocket([WebSocketDisconnect()])

    asyncio.run(_websocket_endpoint(manager, lambda *_args: None)(websocket))

    assert websocket.close_codes == []
    _assert_disconnected_once(manager, websocket)


def test_handler_error_after_connect_removes_socket_once():
    async def failing_handler(_websocket, _data):
        raise RuntimeError("handler failure")

    manager = _FakeConnectionManager()
    websocket = _FakeWebSocket([{"type": "message"}])

    asyncio.run(_websocket_endpoint(manager, failing_handler)(websocket))

    assert websocket.close_codes == []
    _assert_disconnected_once(manager, websocket)


def test_ticket_is_single_use_even_in_concurrent_verification():
    from concurrent.futures import ThreadPoolExecutor
    from modules.auth.service import AuthService

    service = AuthService(ws_auth_secret="test")
    ticket = service.issue_ws_ticket("user")
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(service.verify_ws_ticket, [ticket] * 16))
    assert results.count("user") == 1
    assert results.count(None) == 15


def test_oversized_utf8_message_closes_socket(monkeypatch):
    monkeypatch.setenv("WS_MAX_MESSAGE_BYTES", "10")
    manager = _FakeConnectionManager()
    websocket = _FakeWebSocket([{"text": "Ã©" * 10}])
    asyncio.run(_websocket_endpoint(manager, lambda *_args: None)(websocket))
    assert websocket.close_codes == [1009]
    _assert_disconnected_once(manager, websocket)


def test_ticket_is_single_use():
    from modules.auth.service import AuthService
    service = AuthService(ws_auth_secret="test")
    ticket = service.issue_ws_ticket("user")
    assert service.verify_ws_ticket(ticket) == "user"
    assert service.verify_ws_ticket(ticket) is None


def test_per_user_connection_limit_and_release(monkeypatch):
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "1")
    monkeypatch.setenv("WS_MAX_CONNECTIONS_TOTAL", "20")

    async def run():
        manager = _FakeConnectionManager()
        entered = asyncio.Event()
        release = asyncio.Event()

        class WaitingSocket(_FakeWebSocket):
            async def receive_text(self):
                entered.set()
                await release.wait()
                raise WebSocketDisconnect()

        endpoint = _websocket_endpoint(manager, lambda *_args: None)
        first = WaitingSocket([])
        first_task = asyncio.create_task(endpoint(first))
        await entered.wait()
        rejected = WaitingSocket([])
        await endpoint(rejected)
        assert rejected.close_codes == [1013]
        release.set()
        await first_task
        replacement = WaitingSocket([])
        replacement_task = asyncio.create_task(endpoint(replacement))
        await asyncio.sleep(0)
        release.set()
        await replacement_task
        assert replacement.close_codes == []

    asyncio.run(run())


def test_total_connection_limit(monkeypatch):
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "20")
    monkeypatch.setenv("WS_MAX_CONNECTIONS_TOTAL", "1")

    async def run():
        manager = _FakeConnectionManager()
        entered = asyncio.Event()
        release = asyncio.Event()

        class WaitingSocket(_FakeWebSocket):
            async def receive_text(self):
                entered.set()
                await release.wait()
                raise WebSocketDisconnect()

        endpoint = _websocket_endpoint(manager, lambda *_args: None)
        first = WaitingSocket([])
        first_task = asyncio.create_task(endpoint(first))
        await entered.wait()
        other = WaitingSocket([])
        other.headers["sec-websocket-protocol"] = "mssg-ticket.ticket"
        await endpoint(other)
        assert other.close_codes == [1013]
        release.set()
        await first_task

    asyncio.run(run())
