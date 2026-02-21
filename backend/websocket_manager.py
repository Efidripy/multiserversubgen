"""
WebSocket Manager для real-time обновлений
"""
import asyncio
import json
import logging
from typing import Set, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("websocket_manager")


class ConnectionManager:
    """Управление WebSocket соединениями"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        
    async def connect(self, websocket: WebSocket):
        """Принять новое соединение"""
        await websocket.accept()
        self.active_connections.add(websocket)
        self.subscriptions[websocket] = set()
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")
        
    def disconnect(self, websocket: WebSocket):
        """Отключить соединение"""
        self.active_connections.discard(websocket)
        self.subscriptions.pop(websocket, None)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
        
    def subscribe(self, websocket: WebSocket, channel: str):
        """Подписать клиента на канал"""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].add(channel)
            logger.debug(f"Client subscribed to: {channel}")
            
    def unsubscribe(self, websocket: WebSocket, channel: str):
        """Отписать клиента от канала"""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].discard(channel)
            logger.debug(f"Client unsubscribed from: {channel}")
            
    async def send_personal(self, message: Dict[str, Any], websocket: WebSocket):
        """Отправить сообщение конкретному клиенту"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            
    async def broadcast(self, message: Dict[str, Any], channel: str = None):
        """Отправить сообщение всем подключенным клиентам или в канал"""
        disconnected = set()
        
        for connection in self.active_connections:
            # Если указан канал, отправляем только подписанным
            if channel and channel not in self.subscriptions.get(connection, set()):
                continue
                
            try:
                await connection.send_json(message)
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
