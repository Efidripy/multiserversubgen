"""
WebSocket Manager для real-time обновлений
"""
import asyncio
import logging
from typing import Set, Dict, Any
from fastapi import WebSocket

import orjson

logger = logging.getLogger("websocket_manager")


class ConnectionManager:
    """Управление WebSocket соединениями"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        self.connection_roles: Dict[WebSocket, str] = {}
        self._activity_callback = None

    def set_activity_callback(self, callback):
        """Установить callback для уведомления о WebSocket активности"""
        self._activity_callback = callback

    def _notify_activity(self):
        """Уведомить о WebSocket активности"""
        if self._activity_callback:
            try:
                self._activity_callback()
            except Exception as e:
                logger.error(f"Activity callback error: {e}")

    async def connect(self, websocket: WebSocket, *, accept: bool = True, user: str = "", role: str = "viewer"):
        """Принять новое соединение"""
        if accept:
            await websocket.accept()
        self.active_connections.add(websocket)
        self.subscriptions[websocket] = set()
        self.connection_roles[websocket] = role
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")
        self._notify_activity()

    async def _send_json(self, websocket: WebSocket, message: Dict[str, Any]):
        await websocket.send_text(orjson.dumps(message).decode("utf-8"))
        
    def disconnect(self, websocket: WebSocket):
        """Отключить соединение"""
        self.active_connections.discard(websocket)
        self.subscriptions.pop(websocket, None)
        self.connection_roles.pop(websocket, None)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
        
    def subscribe(self, websocket: WebSocket, channel: str):
        """Подписать клиента на канал"""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].add(channel)
            logger.debug(f"Client subscribed to: {channel}")
            self._notify_activity()
            
    def unsubscribe(self, websocket: WebSocket, channel: str):
        """Отписать клиента от канала"""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].discard(channel)
            logger.debug(f"Client unsubscribed from: {channel}")

    @staticmethod
    def has_channel_access(role: str, minimum_role: str) -> bool:
        ranks = {"viewer": 1, "operator": 2, "admin": 3}
        return ranks.get(role, 0) >= ranks.get(minimum_role, 99)
            
    async def send_personal(self, message: Dict[str, Any], websocket: WebSocket):
        """Отправить сообщение конкретному клиенту"""
        try:
            await self._send_json(websocket, message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """Отправить сообщение всем подключенным клиентам или в канал"""
        disconnected = set()
        
        for connection in list(self.active_connections):
            # Если указан канал, отправляем только подписанным
            if channel and channel not in self.subscriptions.get(connection, set()):
                continue
                
            try:
                await self._send_json(connection, message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")
                disconnected.add(connection)
                
        # Очистка отключенных соединений
        for conn in disconnected:
            self.disconnect(conn)
            
    async def broadcast_server_status(self, status_data: Dict[str, Any]):
        """Отправить обновление статуса серверов"""
        message = {
            "type": "server_status",
            "data": status_data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.broadcast(message, channel="server_status")
        
    async def broadcast_traffic_update(self, traffic_data: Dict[str, Any]):
        """Отправить обновление трафика"""
        message = {
            "type": "traffic_update",
            "data": traffic_data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.broadcast(message, channel="traffic")
        
    async def broadcast_client_update(self, client_data: Dict[str, Any]):
        """Отправить обновление списка клиентов"""
        client_data = _redact_sensitive(client_data)
        message = {
            "type": "client_update",
            "data": client_data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.broadcast(message, channel="clients")
        
    async def broadcast_inbound_update(self, inbound_data: Dict[str, Any]):
        """Отправить обновление inbound"""
        message = {
            "type": "inbound_update",
            "data": inbound_data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.broadcast(message, channel="inbounds")


# Глобальный менеджер соединений
manager = ConnectionManager()


_SENSITIVE_KEY_PARTS = (
    "password", "secret", "privatekey", "private_key", "token", "bearer",
    "totp", "authorization", "cookie", "credential",
)


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if any(part in str(key).lower().replace("-", "_") for part in _SENSITIVE_KEY_PARTS)
            else _redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


async def handle_websocket_message(websocket: WebSocket, message: Dict[str, Any]):
    """Обработка входящих WebSocket сообщений"""
    msg_type = message.get("type")
    
    if msg_type == "subscribe":
        channel = message.get("channel")
        if channel:
            manager.subscribe(websocket, channel)
            await manager.send_personal({
                "type": "subscribed",
                "channel": channel,
                "status": "success"
            }, websocket)
            
    elif msg_type == "unsubscribe":
        channel = message.get("channel")
        if channel:
            manager.unsubscribe(websocket, channel)
            await manager.send_personal({
                "type": "unsubscribed",
                "channel": channel,
                "status": "success"
            }, websocket)
            
    elif msg_type == "ping":
        await manager.send_personal({
            "type": "pong",
            "timestamp": asyncio.get_event_loop().time()
        }, websocket)
        
    else:
        logger.warning(f"Unknown message type: {msg_type}")
